import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadixSelect, RadixSelectContent, RadixSelectItem, RadixSelectTrigger, RadixSelectValue } from '@/components/ui/radix-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogBody, DialogFooter } from '@/components/ui/dialog';
import { toast } from 'sonner';
import { extractApiError } from '@/lib/error-utils';
import { UserPlus, ShieldCheckered, UsersThree, Trash } from '@phosphor-icons/react';
import { api } from '@/services/api';
import { useAuth } from '@/contexts/AuthContext';

interface UserFormData {
  username: string;
  email: string;
  password: string;
  password_confirm: string;
  first_name: string;
  last_name: string;
  role: 'ADMIN' | 'PROCESSOR' | 'ISSUER';
}

export interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  role_display: string;
  is_active: boolean;
}

export default function UserManagementPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [userToDelete, setUserToDelete] = useState<User | null>(null);

  const { register, handleSubmit, reset, watch, setValue, formState: { errors } } = useForm<UserFormData>();

  // Fetch users
  const { data: usersResponse, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const response = await api.get('/users/');
      return response.data;
    },
  });

  // Extract users array from paginated response
  const users = usersResponse?.results || [];

  // Create user mutation
  const createUserMutation = useMutation({
    mutationFn: async (data: UserFormData) => {
      const response = await api.post('/users/', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      toast.success('User created successfully');
      reset();
      setShowForm(false);
    },
    onError: (error: any) => {
      toast.error(extractApiError(error, 'Failed to create user'));
    },
  });

  // Delete user mutation
  const deleteUserMutation = useMutation({
    mutationFn: async (userId: number) => {
      await api.delete(`/users/${userId}/`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      toast.success('User deactivated successfully');
      setUserToDelete(null);
    },
    onError: (error: any) => {
      toast.error(extractApiError(error, 'Failed to deactivate user'));
    },
  });

  const onSubmit = (data: UserFormData) => {
    if (data.password !== data.password_confirm) {
      toast.error('Passwords do not match');
      return;
    }
    createUserMutation.mutate(data);
  };

  const handleDeleteConfirm = () => {
    if (userToDelete) {
      deleteUserMutation.mutate(userToDelete.id);
    }
  };

  const getRoleBadgeVariant = (role: string) => {
    switch (role) {
      case 'ADMIN': return 'destructive';
      case 'PROCESSOR': return 'default';
      case 'ISSUER': return 'secondary';
      default: return 'outline';
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">User Management</h1>
          <p className="text-gray-600 dark:text-gray-400">Register and manage system users</p>
        </div>
        <Button onClick={() => setShowForm(!showForm)}>
          <UserPlus className="mr-2 h-4 w-4" />
          {showForm ? 'Cancel' : 'Register New User'}
        </Button>
      </div>

      {/* Registration Form */}
      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle>Register New User</CardTitle>
            <CardDescription>Create a new user account with assigned role</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Username */}
                <div className="space-y-2">
                  <Label htmlFor="username">Username *</Label>
                  <Input
                    id="username"
                    {...register('username', { required: 'Username is required' })}
                    placeholder="username"
                  />
                  {errors.username && (
                    <p className="text-sm text-destructive">{errors.username.message}</p>
                  )}
                </div>

                {/* Email */}
                <div className="space-y-2">
                  <Label htmlFor="email">Email *</Label>
                  <Input
                    id="email"
                    type="email"
                    {...register('email', {
                      required: 'Email is required',
                      pattern: { value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: 'Invalid email' }
                    })}
                    placeholder="user@example.com"
                  />
                  {errors.email && (
                    <p className="text-sm text-destructive">{errors.email.message}</p>
                  )}
                </div>

                {/* First Name */}
                <div className="space-y-2">
                  <Label htmlFor="first_name">First Name *</Label>
                  <Input
                    id="first_name"
                    {...register('first_name', { required: 'First name is required' })}
                  />
                  {errors.first_name && (
                    <p className="text-sm text-destructive">{errors.first_name.message}</p>
                  )}
                </div>

                {/* Last Name */}
                <div className="space-y-2">
                  <Label htmlFor="last_name">Last Name *</Label>
                  <Input
                    id="last_name"
                    {...register('last_name', { required: 'Last name is required' })}
                  />
                  {errors.last_name && (
                    <p className="text-sm text-destructive">{errors.last_name.message}</p>
                  )}
                </div>

                {/* Role */}
                <div className="space-y-2">
                  <Label htmlFor="role">Role *</Label>
                  <RadixSelect onValueChange={(value) => setValue('role', value as any)}>
                    <RadixSelectTrigger>
                      <RadixSelectValue placeholder="Select role" />
                    </RadixSelectTrigger>
                    <RadixSelectContent>
                      <RadixSelectItem value="ADMIN">
                        <div className="flex items-center gap-2">
                          <ShieldCheckered className="h-4 w-4" />
                          Administrator
                        </div>
                      </RadixSelectItem>
                      <RadixSelectItem value="PROCESSOR">
                        <div className="flex items-center gap-2">
                          <UsersThree className="h-4 w-4" />
                          Processor
                        </div>
                      </RadixSelectItem>
                      <RadixSelectItem value="ISSUER">
                        <div className="flex items-center gap-2">
                          <UsersThree className="h-4 w-4" />
                          Issuer
                        </div>
                      </RadixSelectItem>
                    </RadixSelectContent>
                  </RadixSelect>
                  {errors.role && (
                    <p className="text-sm text-destructive">{errors.role.message}</p>
                  )}
                </div>

                {/* Password */}
                <div className="space-y-2">
                  <Label htmlFor="password">Password *</Label>
                  <Input
                    id="password"
                    type="password"
                    {...register('password', {
                      required: 'Password is required',
                      minLength: { value: 8, message: 'Password must be at least 8 characters' }
                    })}
                    placeholder="••••••••"
                  />
                  {errors.password && (
                    <p className="text-sm text-destructive">{errors.password.message}</p>
                  )}
                </div>

                {/* Confirm Password */}
                <div className="space-y-2">
                  <Label htmlFor="password_confirm">Confirm Password *</Label>
                  <Input
                    id="password_confirm"
                    type="password"
                    {...register('password_confirm', {
                      required: 'Please confirm password',
                      validate: (value) => value === watch('password') || 'Passwords do not match'
                    })}
                    placeholder="••••••••"
                  />
                  {errors.password_confirm && (
                    <p className="text-sm text-destructive">{errors.password_confirm.message}</p>
                  )}
                </div>
              </div>

              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setShowForm(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={createUserMutation.isPending}>
                  {createUserMutation.isPending ? 'Creating...' : 'Create User'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Users Table */}
      <Card>
        <CardHeader>
          <CardTitle>Registered Users</CardTitle>
          <CardDescription>Manage system users and their roles</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : users.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <UsersThree className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>No users registered yet.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Username</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users?.map((user: User) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">{user.username}</TableCell>
                    <TableCell>{user.first_name} {user.last_name}</TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>
                      <Badge variant={getRoleBadgeVariant(user.role) as any}>
                        {user.role_display}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? 'default' : 'secondary'}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setUserToDelete(user)}
                        disabled={user.id === currentUser?.id || !user.is_active}
                        className="text-red-500 hover:text-red-700 hover:bg-[rgb(var(--color-destructive))/0.1] dark:hover:bg-red-950"
                      >
                        <Trash className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Deletion Confirmation Dialog */}
      <Dialog open={!!userToDelete} onOpenChange={(open) => !open && setUserToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Deactivation</DialogTitle>
          </DialogHeader>
          <DialogBody>
            <DialogDescription>
              Are you sure you want to deactivate the user <strong>{userToDelete?.username}</strong>?
              This user will no longer be able to log in, but their historical data (transactions) will be preserved.
            </DialogDescription>
          </DialogBody>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setUserToDelete(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteUserMutation.isPending}
            >
              {deleteUserMutation.isPending ? 'Deactivating...' : 'Deactivate User'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
